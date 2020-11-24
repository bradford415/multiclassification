"""
 main.py
"""
import pandas as pd
import sys
import os
import logging
import argparse
import utils
import dataset
import plots
import torch
import preprocessing
import numpy as np 
from datetime import datetime
from plots import Plotter
from torch.utils import data
from definitions import INPUT_DIR
from definitions import OUTPUT_DIR


def train(model, device, train_generator, optimizer, loss_fn, epoch, batch_size, loss_avgmeter, train_stats):
    """
     Train the network and collect accuracy and loss in dataframes. Different loss functions will be 
     used if it is a binary prediction or multiclass prediction.
    """
    model.train() # Set model to train mode (default mode)

    total_items = 0
    acc = 0.0
    loss= 0.0
    for data, target in train_generator:
        total_items += target.shape[0] 
        data = data.unsqueeze(1).float()
        optimizer.zero_grad() # Zero out the gradients
        prediction = model(data)
        #if is_binary:
        #    target = target.unsqueeze(1).float()
        #    acc += utils.multi_accuracy(target, prediction)
        #    loss = loss_fn(prediction, target.float())
        #else:
        acc += utils.multi_accuracy(target, prediction)
        loss = loss_fn(prediction, target.long())
        loss.backward() # Compute gradients
        optimizer.step() # Upate weights

    # Calculate loss per epoch
    loss_avgmeter.update(loss.item(), batch_size)
    acc_avg = acc/total_items
    train_stats.append(pd.DataFrame([[acc_avg, loss_avgmeter.avg]], columns=['accuracy', 'loss']), ignore_index=True)


def test(model, device, test_generator, optimizer, loss_fn, epoch, batch_size, loss_avgmeter, test_stats, train_stats, logger):
    """
     Test the model with the test dataset. Only doing forward passes, backpropagrations should not be applied
    """
    model.eval() # Set model to eval mode - required for dropout and norm layers

    total_items = 0
    acc = 0.0
    loss= 0.0
    loss_avgmeter.reset()
    with torch.no_grad():
        for data, target in test_generator:
            total_items += target.shape[0]
            data = data.unsqueeze(1).float()
            prediction = model(data)
            #if is_binary:
            #    target = target.unsqueeze(1).float()
            #    acc += utils.multi_accuracy(target, prediction)
            #    loss = loss_fn(prediction, target.float())
            #else:
            acc += utils.multi_accuracy(target, prediction)
            loss = loss_fn(prediction, target.long())
            loss_avgmeter.update(loss.item(), batch_size)

    loss_avgmeter.update(loss.item(), batch_size)
    acc_avg = acc/total_items
    test_stats.append(pd.DataFrame([[acc_avg, loss_avgmeter.avg]], columns=['accuracy', 'loss']), ignore_index=True)

    # write training log to the log file
    logger.info('Epoch: %d Training Loss: %2.5f Test Accuracy : %2.3f Accurate Count: %d Total Items :%d '% (epoch, train_stats.iloc[epoch]['loss'], acc_avg, acc, total_items))
    loss_avgmeter.reset()


def forward(model, test_generator, predict_list, target_list):
    """One forward pass through the model. Mostly used to get confusion matrix values"""
    with torch.no_grad():
        for data, target in test_generator:

            data = data.unsqueeze(1).float()
            prediction = model(data)
            #if is_binary:
            #    actual_labels = actual_labels.unsqueeze(1).float()
            #    pred_labels_sigmoid = torch.nn.Sigmoid(pred_labels)
            #    pred_labels_tags = (pred_labels_sigmoid >= 0.5).eq(actual_labels)
            #else:
            prediction_softmax = torch.softmax(prediction, dim=1)
            _, prediction_tags = torch.max(prediction_softmax, dim=1)
            
            predict_list.append(prediction_tags)
            target_list.append(target)
            
    predict_list = [j for val in predict_list for j in val]
    target_list = [j for val in target_list for j in val]


def main():
    # Maybe delete this ?
    group = 'lung'

    parser = argparse.ArgumentParser(description='classifier')
    parser.add_argument('--sample_file', type=str, default='lung.emx.txt', help="the name of the GEM organized by samples (columns) by genes (rows)")
    parser.add_argument('--label_file', type=str, default='sample_condition.txt', help="name of the label file: two columns that maps the sample to the label")
    parser.add_argument('--output_name', type=str, default='tissue-run-1', help="name of the output directory to store the output files")
    #parser.add_argument('--overwrite_output', type=bool, default=False, help="overwrite the output directory file if it already exists")
    parser.add_argument('--batch_size', type=int, default=16, help="size of batches to split data")
    parser.add_argument('--max_epoch', type=int, default=100, help="number of passes through a dataset")
    parser.add_argument('--learning_rate', type=int, default=0.001, help="controls the rate at which the weights of the model update")
    parser.add_argument('--test_split', type=int, default=0.3, help="percentage of test data, the train data will be the remaining data")
    #parser.add_argument('--input_num_classes', type=int, default=10) # binning value, will come back to later when working with discrete data
    parser.add_argument('--continuous_discrete', type=str, default='continuous', help="type of data in the sample file, typically RNA will be continous and DNA will be discrete")
    parser.add_argument('--plot_results', type=bool, default=True, help="plots the sample distribution, training/test accuracy/loss, and confusion matrix")

    args = parser.parse_args()

    #If data is discrete, data should only range between 0-3
    #if args.continuous_discrete == "discrete":
        #args.input_num_classes = 4

    # Initialize file paths and create output folder
    LABEL_FILE = os.path.join(INPUT_DIR, args.label_file)
    SAMPLE_FILE = os.path.join(INPUT_DIR, args.sample_file)
    OUTPUT_DIR_FINAL = os.path.join(OUTPUT_DIR, "-" + args.output_name + "-" + str(datetime.today().strftime('%Y-%m-%d-%H:%M')))
    if not os.path.exists(OUTPUT_DIR_FINAL):
        os.mkdirs(OUTPUT_DIR_FINAL)

    # Create log file to keep track of model parameters
    logging.basicConfig(filename=os.path.join(OUTPUT_DIR_FINAL,'classifier.log'),
                        filemode='w',
                        format='%(message)s',
                        level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info('Classifer log file for ' + args.sample_file + ' - Started on ' + str(datetime.today().strftime('%Y-%m-%d-%H:%M')) + '\n')
    logger.info('Batch size: %d', args.batch_size)
    logger.info('Number of epochs: %d', args.max_epoch)
    logger.info('Learning Rate: %d', args.learning_rate)
    logger.info('Sample filename: ' + args.sample_file)
    logger.info('Output directory: ' + args.output_name)

    if args.continuous_discrete != 'continuous' and args.continuous_discrete != 'discrete':
        logger.error("ERROR: check that the continuous_discrete argument is spelled correctly.")
        logger.error("       only continuous or discrete data can be processed.")
        sys.exit("\nCommand line argument error. Please check the log file.\n")

    # Load matrix
    matrix_df = pd.read_csv(SAMPLE_FILE, sep='\t', index_col=[0])

    # Get number of samples and list of labels - log this information
    column_names = ("sample", "label")
    labels_df = pd.read_csv(LABEL_FILE, names=column_names, delim_whitespace=True, header=None)
    labels, class_weights = preprocessing.labels_and_weights(labels_df)
    args.output_num_classes = len(labels)
    #is_binary = False
    #if len(labels) == 2:
    #    is_binary = True
    #    args.output_num_classess = 1

    # Define paramters
    batch_size = args.batch_size
    max_epoch = args.max_epoch
    learning_rate = args.learning_rate #5e-4
    num_features = len(matrix_df.index)
    num_classes = len(labels)

    # Setup model
    model = utils.Net(input_seq_length=num_features,
                  output_num_classes=num_classes)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, verbose=True, patience=50)
    loss_fn = torch.nn.CrossEntropyLoss()#(weight=class_weights)

    #if is_binary:
    #    loss_fn = torch.nn.BCEWithLogitsLoss()
    #else:

    logger.info('Number of samples: %d\n', args.seq_length)
    logger.info('Labels: ')
    for i in range(len(labels)):
        logger.info('       %d - %s', i, labels[i])
    
    # Replace missing data with the global minimum of the dataset
    val_min, val_max = np.nanmin(matrix_df), np.nanmax(matrix_df)
    matrix_df.fillna(val_min, inplace=True)

    graphs = plots.Plotter(OUTPUT_DIR_FINAL)
    graphs.density(matrix_df)

    # Transposing matrix to align with label file
    matrix_transposed_df = matrix_df.T
    train_data, test_data = preprocessing.split_data(matrix_transposed_df, labels_df, args.test_split, num_classes)

    # Convert tuple of df's to tuple of np's
    # Allows the dataset class to access w/ data[][] instead of data[].iloc[]
    train_data_np = (train_data[0].values, train_data[1].values)
    test_data_np = (test_data[0].values, test_data[1].values)

    train_dataset = dataset.Dataset(train_data_np)
    test_dataset = dataset.Dataset(test_data_np)
    train_generator = data.DataLoader(train_dataset, batch_size=batch_size, drop_last=False)
    test_generator = data.DataLoader(test_dataset, batch_size=batch_size, drop_last=False)
    # drop_last=True would drop the last batch if the sample size is not divisible by the batch size

    logger.info('\nTraining size: %d \nTesting size: %d', len(train_dataset), len(test_dataset))
    net = utils.Net(input_seq_length=args.seq_length,
                   input_num_classes=args.input_num_classes,
                   output_num_classes=args.output_num_classes)
    # Characterize dataset
    # drop_last adjusts the last batch size when the given batch size is not divisible by the number of samples
    batch_size = args.batch_size
    training_generator = data.DataLoader(train_dataset, batch_size=batch_size, drop_last=False)
    val_generator = data.DataLoader(test_dataset, batch_size=batch_size, drop_last=False)

    # Create variables to store accuracy and loss
    loss_avgmeter = utils.AverageMeter()
    loss_avgmeter.reset()
    summary_file = pd.DataFrame([], columns=['Epoch', 'Training Loss', 'Accuracy', 'Accurate Count', 'Total Items'])
    train_stats = pd.DataFrame([], columns=['accuracy', 'loss'])
    test_stats = pd.DataFrame([], columns=['accuracy', 'loss'])

    # Train and test the model
    for epoch in range(args.max_epoch):
        train(model, device, train_generator, optimizer, loss_fn, epoch, batch_size, loss_avgmeter, train_stats)
        test(model, device, test_generator, optimizer, loss_fn, epoch, batch_size, loss_avgmeter, test_stats)
        scheduler.step()

    # All epochs finished - Below is used for testing the network, plots and saving results
    if(args.plot_results):
        # Lists to store confusion matrix values
        predict_list = []
        target_list = []
        forward(model, test_generator, predict_list, target_list)

        graphs.accuracy(train_stats, test_stats, graphs_title=args.sample_file)
        graphs.confusion(predict_list, target_list, labels, cm_title=args.sample_file)

    #summary_file.to_csv(RESULTS_FILE, sep='\t', index=False)
    logger.info('\nFinal Accuracy: %2.3f', test_stats.iloc[epoch]['accuracy'])
    logger.info('\nFinished at  ' + str(datetime.today().strftime('%Y-%m-%d-%H:%M')))

if __name__ == '__main__':
    main()